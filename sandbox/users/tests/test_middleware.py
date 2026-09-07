"""§8.2's carried debt: staff owe TOTP before the console opens."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import override_settings
from django.urls import reverse

from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

CONSOLE = "ohc:queue"


@pytest.fixture
def staff(db):
    return UserFactory(email="ops@nha.gov.in", is_staff=True)


def test_a_staff_account_without_totp_is_sent_to_set_it_up(client, db):
    """The regression this closes: replacing `users/` dropped the middleware,
    so `STAFF_MFA_REQUIRED` guarded nothing."""
    without = UserFactory(
        email="new@nha.gov.in",
        is_staff=True,
        mfa=False,
    )
    client.force_login(without)

    response = client.get(reverse(CONSOLE))

    assert response.status_code == HTTPStatus.FOUND
    assert "totp" in response.url


def test_a_staff_account_with_totp_passes(client, staff):
    client.force_login(staff)

    assert client.get(reverse(CONSOLE)).status_code == HTTPStatus.OK


def test_the_destination_is_exempt_so_the_redirect_cannot_loop():
    """allauth's own flow takes over under /accounts/; this only has to stop
    sending a user there for ever."""
    from sandbox.users.middleware import StaffMfaRequiredMiddleware  # noqa: PLC0415

    exempt = StaffMfaRequiredMiddleware._is_exempt  # noqa: SLF001

    assert exempt("/accounts/2fa/totp/activate/") is True
    assert exempt("/accounts/logout/") is True
    assert exempt("/static/css/app.css") is True
    assert exempt(reverse(CONSOLE)) is False


def test_an_applicant_is_not_asked_for_totp(client, db):
    """The applicant half of the original middleware waits on the user-level
    contact fields, so a vendor owes nothing here yet."""
    applicant = UserFactory(email="dev@vendor.in")
    client.force_login(applicant)

    response = client.get(reverse("experiences:list"))

    assert "totp" not in getattr(response, "url", "")


def test_an_anonymous_visitor_is_untouched(client, db):
    assert client.get(reverse("account_login")).status_code == HTTPStatus.OK


@override_settings(STAFF_MFA_REQUIRED=False)
def test_the_setting_can_be_turned_off_for_local_work(client, db):
    """`guards.py` refuses this combination with DEBUG off."""
    without = UserFactory(
        email="new@nha.gov.in",
        is_staff=True,
        mfa=False,
    )
    client.force_login(without)

    assert client.get(reverse(CONSOLE)).status_code == HTTPStatus.OK
