"""The shell's own gate (C10).

The route matrix proves every URL is *guarded*. It cannot prove any of them is
*reachable*, and it says nothing about what the chrome offers. Both failures
have shipped here: a screen with no inbound link, and a nav item whose target
answers the reader with a 403 — each while the route tests were green.

So this module asserts the two properties the matrix cannot:

1. Every link a shell renders for an actor actually answers that actor.
2. Every screen that exists is reachable without typing a URL.

There are two shells, and they do not mix: `layouts/app.html` carries `#app-nav`
for vendors, `layouts/staff.html` carries `#staff-nav` for the review team.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from sandbox.experiences.registry import registry
from tests.conftest import ORG_MEMBER
from tests.conftest import REVIEWER
from tests.conftest import STAFF
from tests.test_route_gates import live_url_names

pytestmark = pytest.mark.django_db

HTTP_OK = 200
DENIED_CODES = frozenset({403, 404})

APP_NAV = b"app-nav"
CONSOLE_NAV = b"staff-nav"

#: Actor, the screen they land on after signing in, and the nav that screen
#: renders. A reviewer and a superuser share the console but not their
#: `ReviewRole` rows, so both are exercised.
SHELLS = [
    (ORG_MEMBER, "dashboard", APP_NAV),
    (REVIEWER, "staff:queue", CONSOLE_NAV),
    (STAFF, "staff:queue", CONSOLE_NAV),
]

#: Screens with no inbound link anywhere, and why each needs none.
#:
#: Everything else must be linked from a template, or a user can only reach it
#: by typing the path.
NO_INBOUND_LINK = {
    # `LOGIN_REDIRECT_URL`. allauth sends you here and it only ever redirects;
    # a nav item would have to promise a destination it does not have.
    "users:redirect",
    # A redirect kept so `User.get_absolute_url()` resolves. `users:profile` is
    # the screen, and the settings rail is where it is linked from.
    "users:detail",
    # Reached from the emailed invitation, by someone who cannot sign in yet.
    "organisations:invitation-accept",
    # Engine machinery no ABDM form has asked for: the vendor detail template
    # renders form links but not form actions, because no registered form
    # declares one. `test_no_form_action_ships_without_a_way_to_reach_it` is
    # what stops that staying true once one does.
    "experiences:form-action",
}

#: allauth owns these screens and links them from its own flows.
_ALLAUTH_PREFIXES = ("account_", "socialaccount_", "mfa_")

_URL_TAG = re.compile(r"{%\s*url\s*['\"]([^'\"]+)['\"]")
_HREF = re.compile(rb'href="([^"]+)"')
_TEMPLATES = Path(settings.APPS_DIR) / "templates"


def _shell_nav(html: bytes, nav_id: bytes) -> bytes:
    start = html.index(b'id="' + nav_id + b'"')
    return html[start : html.index(b"</nav>", start)]


def _nav_links(html: bytes, nav_id: bytes) -> list[str]:
    """Every href inside a shell's <nav>, in document order."""
    return [href.decode() for href in _HREF.findall(_shell_nav(html, nav_id))]


def _internal(links: list[str]) -> list[str]:
    return [href for href in links if href.startswith("/")]


def _marked_items(nav: bytes) -> list[bytes]:
    return [
        anchor
        for anchor in re.findall(rb"<a\s[^>]*>", nav)
        if b"aria-current" in anchor
    ]


# What the shell offers


@pytest.mark.parametrize(("actor", "landing", "nav_id"), SHELLS)
def test_signing_in_leads_to_the_shell_the_actor_works_in(
    clients,
    actor,
    landing,
    nav_id,
):
    """A reviewer who lands in the vendor hub is offered a sidebar full of
    pages that are not theirs, and reaches the console only by typing its URL.
    """
    response = clients[actor].get(reverse("users:redirect"), follow=True)

    assert response.redirect_chain[-1][0] == reverse(landing)
    assert b'id="' + nav_id + b'"' in response.content


@pytest.mark.parametrize(("actor", "landing", "nav_id"), SHELLS)
def test_every_link_the_shell_offers_answers_the_actor(
    clients,
    actor,
    landing,
    nav_id,
):
    """The defect this repo has shipped: a link to a screen the reader cannot
    open. Following each one is the only way to know."""
    client = clients[actor]
    response = client.get(reverse(landing))
    assert response.status_code == HTTP_OK

    links = _internal(_nav_links(response.content, nav_id))
    assert links, "the sidebar rendered no links at all"

    for href in links:
        followed = client.get(href, follow=True)
        assert followed.status_code not in DENIED_CODES, (
            f"{actor} is offered {href} in the sidebar but gets "
            f"{followed.status_code} on following it"
        )
        # A 200 is not enough: a nav item must point at a page, not at one of
        # the htmx fragments that answer from the same URL space.
        assert APP_NAV in followed.content or CONSOLE_NAV in followed.content, (
            f"{actor} follows {href} and lands outside both shells"
        )


@pytest.mark.parametrize(
    ("destination", "item"),
    [
        ("dashboard", b"nav-dashboard"),
        ("events:list", b"nav-events"),
        ("experiences:list", b"nav-applications"),
        ("support:list", b"nav-support"),
        ("organisations:detail", b"nav-settings"),
        # Profile lives under Settings rather than beside it, so the section
        # stays lit while the settings rail marks the tab.
        ("users:profile", b"nav-settings"),
    ],
)
def test_the_vendor_shell_marks_where_you_are(clients, destination, item):
    response = clients[ORG_MEMBER].get(reverse(destination))

    marked = _marked_items(_shell_nav(response.content, APP_NAV))

    assert len(marked) == 1, f"{destination} lights {len(marked)} nav items"
    assert b'id="' + item + b'"' in marked[0]


@pytest.mark.parametrize(
    ("destination", "item"),
    [
        ("staff:queue", b"staff-nav-queue"),
        ("staff:organisations", b"staff-nav-organisations"),
        ("staff:applications", b"staff-nav-applications"),
        ("staff:events", b"staff-nav-events"),
    ],
)
def test_the_console_marks_where_you_are(clients, destination, item):
    response = clients[REVIEWER].get(reverse(destination))

    marked = _marked_items(_shell_nav(response.content, CONSOLE_NAV))

    assert len(marked) == 1, f"{destination} lights {len(marked)} nav items"
    assert b'id="' + item + b'"' in marked[0]


# Crossing between the two shells


def test_a_staff_member_in_the_vendor_shell_can_get_back_to_the_console(clients):
    """Staff reach that shell through their profile and the MFA screens."""
    response = clients[STAFF].get(reverse("users:profile"))

    assert reverse("staff:queue") in _nav_links(response.content, APP_NAV)


def test_a_vendor_is_never_offered_the_console(clients):
    response = clients[ORG_MEMBER].get(reverse("dashboard"))

    assert reverse("staff:queue") not in _nav_links(response.content, APP_NAV)


def test_a_console_user_can_reach_their_own_account(clients):
    """The rail's user card was inert text, so 2FA and email settings were
    unreachable from the only shell staff ever see."""
    response = clients[REVIEWER].get(reverse("staff:queue"))

    assert reverse("users:profile") in _nav_links(response.content, CONSOLE_NAV)


def test_a_vendor_page_sends_a_staff_member_to_the_console_rather_than_403(clients):
    """Staff routinely hold no membership, so every org-scoped page is closed to
    them. `OrganisationMixin` answers with the console and a message, because a
    403 on a page they were never meant to open reads as breakage.
    """
    response = clients[STAFF].get(reverse("experiences:list"), follow=True)

    assert response.redirect_chain == [(reverse("staff:queue"), 302)]
    assert [str(message) for message in response.context["messages"]] == [
        "That is a vendor page. Here is the Staff console instead.",
    ]


# Reachability


def _linked_url_names() -> set[str]:
    """Every URL name a template links to.

    `{% url %}` is the direct form. A template may also link a record by its own
    `get_absolute_url`, which reverses a name the tag never mentions — so those
    are read off the models rather than allowlisted, which would record the
    claim that a link exists instead of the link itself.
    """
    templates = [(path, path.read_text()) for path in _TEMPLATES.rglob("*.html")]
    linked = {
        match.group(1) for _, source in templates for match in _URL_TAG.finditer(source)
    }
    if any("get_absolute_url" in source for _, source in templates):
        linked |= _absolute_url_targets()
    return linked


def _absolute_url_targets() -> set[str]:
    """The name each model's `get_absolute_url` reverses."""
    targets = set()
    for models in Path(settings.APPS_DIR).rglob("models.py"):
        source = models.read_text()
        for match in re.finditer(r"def get_absolute_url\b", source):
            body = source[match.end() : match.end() + 400]
            found = re.search(r"reverse\(\s*[\"']([^\"']+)[\"']", body)
            if found:
                targets.add(found.group(1))
    return targets


def test_every_screen_has_an_inbound_link():
    linked = _linked_url_names()
    unreachable = sorted(
        name
        for name in live_url_names()
        if name not in linked
        and name not in NO_INBOUND_LINK
        and not name.startswith(("djdt:", *_ALLAUTH_PREFIXES))
    )

    assert not unreachable, (
        f"Screens no template links to: {unreachable}. Give each one an inbound "
        "link, or add it to NO_INBOUND_LINK with the reason it needs none."
    )


def test_no_inbound_link_rows_do_not_outlive_their_urls():
    stale = sorted(NO_INBOUND_LINK - live_url_names())

    assert not stale, f"NO_INBOUND_LINK rows for URLs that no longer exist: {stale}"


def test_no_form_action_ships_without_a_way_to_reach_it():
    """`experiences:form-action` sits in NO_INBOUND_LINK because no registered
    form declares an action. The staff detail template renders them; the vendor
    one does not, so the first vendor-side form action would be unreachable.
    """
    declared = sorted(
        (definition.key, form.key, action.key)
        for definition in registry.all()
        for form in definition.forms
        for action in form.actions
    )

    assert not declared, (
        f"Form actions are declared ({declared}) but the vendor application "
        "detail template links none of them. Render them there and drop "
        "experiences:form-action from NO_INBOUND_LINK."
    )


# The no-JavaScript contract


@pytest.mark.parametrize(
    ("actor", "landing", "drawer"),
    [
        (ORG_MEMBER, "dashboard", b"app-drawer"),
        (REVIEWER, "staff:queue", b"staff-drawer"),
    ],
)
def test_the_mobile_drawer_needs_no_javascript(clients, actor, landing, drawer):
    """The drawer is a checkbox and a label. A script may enhance it; nothing
    may be required to open it."""
    html = clients[actor].get(reverse(landing)).content

    assert b'id="' + drawer + b'"' in html
    assert b'type="checkbox"' in html
    assert b'for="' + drawer + b'"' in html
