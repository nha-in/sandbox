"""The gate on the Staff console, asserted route by route.

This is the security boundary of the whole feature. Every screen under /staff/
reads and writes tickets belonging to *every* vendor with no organisation
scoping at all, so the only thing standing between a signed-in vendor and the
entire support queue is StaffConsoleMixin. These tests exist so that a new
screen added without the mixin fails here rather than in production.

Three properties are pinned:

* anonymous → the login page, because that is a person who has not identified
  themselves yet;
* signed-in but not review team → 403, never a redirect to a login form they are
  already past, and never a mutation;
* review team → through, including to another organisation's ticket, which is the
  one place in the app where cross-organisation reads are the point.

Every mutation is also sent the way a browser with scripting off sends it — no
HX-Request header — and asserted to answer with a real redirect.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from sandbox.events.models import Event
from sandbox.events.tests.factories import EventFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.support.models import Category
from sandbox.support.models import Priority
from sandbox.support.models import Status
from sandbox.support.models import Ticket
from sandbox.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.test import Client

    from sandbox.organisations.models import Organisation
    from sandbox.users.models import User

pytestmark = pytest.mark.django_db

HTMX_HEADERS = {"HX-Request": "true"}


# ── actors ─────────────────────────────────────────────────────────────────


@pytest.fixture
def staff_member(db) -> User:
    return UserFactory.create(
        email="anand@nha.gov.in",
        name="Anand S",
        is_staff=True,
    )


@pytest.fixture
def vendor(db) -> User:
    """A signed-in vendor: a real member of a real organisation, not review team."""
    return MembershipFactory.create(
        organisation__name="Arogya Systems",
        user__email="meera@arogyasystems.in",
        role="owner",
    ).user


@pytest.fixture
def staff_client(sign_in: Callable[[User], Client], staff_member: User) -> Client:
    return sign_in(staff_member)


@pytest.fixture
def vendor_client(sign_in: Callable[[User], Client], vendor: User) -> Client:
    return sign_in(vendor)


# ── fixtures under test ────────────────────────────────────────────────────


def make_ticket(organisation: Organisation, **overrides) -> Ticket:
    fields = {
        "subject": "ABHA link API returns 401 after a token refresh",
        "category": Category.API,
        "priority": Priority.HIGH,
        "status": Status.OPEN,
    }
    return Ticket.objects.create(organisation=organisation, **(fields | overrides))


@pytest.fixture
def other_organisation(db) -> Organisation:
    """A vendor the signed-in vendor has nothing to do with."""
    return OrganisationFactory.create(name="Sunrise Health Systems", onboarded=True)


@pytest.fixture
def ticket(other_organisation: Organisation) -> Ticket:
    return make_ticket(other_organisation)


@pytest.fixture
def event(db) -> Event:
    return EventFactory.create(title="ABDM API office hours")


def read_urls(ticket: Ticket, event: Event) -> list[str]:
    return [
        reverse("staff:queue"),
        reverse("staff:ticket", args=[ticket.reference]),
        reverse("staff:organisations"),
        reverse("staff:organisation", args=[ticket.organisation.slug]),
        reverse("staff:events"),
        reverse("staff:event-create"),
        reverse("staff:event-update", args=[event.slug]),
    ]


def write_urls(ticket: Ticket, event: Event) -> list[str]:
    return [
        reverse("staff:ticket-reply", args=[ticket.reference]),
        reverse("staff:ticket-update", args=[ticket.reference]),
        reverse(
            "staff:organisation-verification",
            args=[ticket.organisation.slug],
        ),
        reverse("staff:event-create"),
        reverse("staff:event-update", args=[event.slug]),
        reverse("staff:event-publish", args=[event.slug]),
    ]


# ── the gate ───────────────────────────────────────────────────────────────


class TestAnonymousAccess:
    """Someone who has not signed in gets the login page, not a 403."""

    def test_every_read_route_sends_them_to_sign_in(
        self,
        client: Client,
        ticket: Ticket,
        event: Event,
    ):
        login_url = reverse("account_login")

        for url in read_urls(ticket, event):
            response = client.get(url)

            assert response.status_code == HTTPStatus.FOUND, url
            assert response.url.startswith(login_url), url

    def test_every_write_route_sends_them_to_sign_in(
        self,
        client: Client,
        ticket: Ticket,
        event: Event,
    ):
        login_url = reverse("account_login")

        for url in write_urls(ticket, event):
            response = client.post(url, {})

            assert response.status_code == HTTPStatus.FOUND, url
            assert response.url.startswith(login_url), url


class TestVendorIsLockedOut:
    """The one that matters: a signed-in vendor may not reach the console."""

    def test_every_read_route_is_a_403(
        self,
        vendor_client: Client,
        ticket: Ticket,
        event: Event,
    ):
        for url in read_urls(ticket, event):
            response = vendor_client.get(url)

            assert response.status_code == HTTPStatus.FORBIDDEN, url

    def test_every_write_route_is_a_403(
        self,
        vendor_client: Client,
        ticket: Ticket,
        event: Event,
    ):
        for url in write_urls(ticket, event):
            response = vendor_client.post(url, {})

            assert response.status_code == HTTPStatus.FORBIDDEN, url

    def test_an_htmx_post_is_refused_the_same_way(
        self,
        vendor_client: Client,
        ticket: Ticket,
        event: Event,
    ):
        """The gate is not a template concern, so htmx cannot get past it."""
        for url in write_urls(ticket, event):
            response = vendor_client.post(url, {}, headers=HTMX_HEADERS)

            assert response.status_code == HTTPStatus.FORBIDDEN, url

    def test_a_vendor_cannot_read_another_organisations_ticket(
        self,
        vendor_client: Client,
        ticket: Ticket,
    ):
        """The console route is the bypass a vendor would reach for."""
        response = vendor_client.get(reverse("staff:ticket", args=[ticket.reference]))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_a_vendor_cannot_read_their_own_ticket_through_the_console(
        self,
        vendor_client: Client,
        vendor: User,
    ):
        """Even their own ticket: the console is not a vendor route at all."""
        mine = make_ticket(vendor.memberships.get().organisation)

        response = vendor_client.get(reverse("staff:ticket", args=[mine.reference]))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestVendorPostsChangeNothing:
    """A refused POST must also be a POST that did not happen."""

    def test_a_refused_reply_writes_no_message(
        self,
        vendor_client: Client,
        ticket: Ticket,
    ):
        url = reverse("staff:ticket-reply", args=[ticket.reference])

        response = vendor_client.post(url, {"body": "Let me in"})

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert not ticket.messages.exists()
        ticket.refresh_from_db()
        assert ticket.status == Status.OPEN
        assert ticket.first_responded_at is None

    def test_a_refused_control_post_moves_nothing(
        self,
        vendor_client: Client,
        ticket: Ticket,
    ):
        url = reverse("staff:ticket-update", args=[ticket.reference])

        response = vendor_client.post(
            url,
            {"status": Status.CLOSED, "priority": Priority.LOW, "assignee": ""},
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        ticket.refresh_from_db()
        assert ticket.status == Status.OPEN
        assert ticket.priority == Priority.HIGH
        assert not ticket.messages.exists()

    def test_a_refused_publish_leaves_the_event_a_draft(
        self,
        vendor_client: Client,
        event: Event,
    ):
        url = reverse("staff:event-publish", args=[event.slug])

        response = vendor_client.post(url, {})

        assert response.status_code == HTTPStatus.FORBIDDEN
        event.refresh_from_db()
        assert event.is_published is False

    def test_a_refused_event_create_writes_no_row(self, vendor_client: Client):
        before = set(Event.objects.values_list("pk", flat=True))

        response = vendor_client.post(
            reverse("staff:event-create"),
            {
                "title": "Vendor-authored event",
                "kind": "webinar",
                "summary": "Should never exist.",
                "starts_at": "2026-09-01T10:00",
                "ends_at": "2026-09-01T11:00",
            },
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert set(Event.objects.values_list("pk", flat=True)) == before


class TestStaffGetsThrough:
    """The mirror image, so a 403 everywhere cannot pass these tests."""

    def test_every_read_route_renders(
        self,
        staff_client: Client,
        ticket: Ticket,
        event: Event,
    ):
        for url in read_urls(ticket, event):
            response = staff_client.get(url)

            assert response.status_code == HTTPStatus.OK, url

    def test_the_queue_crosses_organisations(
        self,
        staff_client: Client,
        other_organisation: Organisation,
    ):
        """The console's whole reason to exist, and why the gate matters."""
        theirs = make_ticket(other_organisation, subject="Sandbox reset wiped records")
        ours = make_ticket(
            OrganisationFactory.create(name="Second Vendor"),
            subject="Rate limits on the sandbox FHIR endpoints",
        )

        response = staff_client.get(reverse("staff:queue"))

        references = {t.reference for t in response.context["tickets"]}
        assert {theirs.reference, ours.reference} <= references


# ── no-JS ──────────────────────────────────────────────────────────────────


class TestWithoutScripting:
    """Every console mutation answers a plain POST with POST → redirect → GET."""

    def test_a_reply_redirects_back_to_the_ticket(
        self,
        staff_client: Client,
        ticket: Ticket,
    ):
        url = reverse("staff:ticket-reply", args=[ticket.reference])

        response = staff_client.post(url, {"body": "Traced it — the refresh call…"})

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("staff:ticket", args=[ticket.reference])
        ticket.refresh_from_db()
        assert ticket.status == Status.AWAITING_VENDOR
        assert ticket.first_responded_at is not None
        assert ticket.messages.get().body.startswith("Traced it")

    def test_a_control_change_redirects_back_to_the_ticket(
        self,
        staff_client: Client,
        staff_member: User,
        ticket: Ticket,
    ):
        url = reverse("staff:ticket-update", args=[ticket.reference])

        response = staff_client.post(
            url,
            {
                "status": Status.RESOLVED,
                "priority": Priority.LOW,
                "assignee": str(staff_member.pk),
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("staff:ticket", args=[ticket.reference])
        ticket.refresh_from_db()
        assert ticket.status == Status.RESOLVED
        assert ticket.priority == Priority.LOW
        assert ticket.assignee == staff_member
        assert ticket.messages.get().is_event

    def test_publishing_redirects_back_to_the_event_list(
        self,
        staff_client: Client,
        event: Event,
    ):
        url = reverse("staff:event-publish", args=[event.slug])

        response = staff_client.post(url, {})

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("staff:events")
        event.refresh_from_db()
        assert event.is_published is True

    def test_unpublishing_redirects_back_to_the_event_list(
        self,
        staff_client: Client,
    ):
        event = EventFactory.create(published=True)
        url = reverse("staff:event-publish", args=[event.slug])

        response = staff_client.post(url, {})

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("staff:events")
        event.refresh_from_db()
        assert event.is_published is False

    def test_an_invalid_reply_is_a_200_with_errors_not_a_redirect(
        self,
        staff_client: Client,
        ticket: Ticket,
    ):
        url = reverse("staff:ticket-reply", args=[ticket.reference])

        response = staff_client.post(url, {"body": ""})

        assert response.status_code == HTTPStatus.OK
        assert not ticket.messages.exists()
