from __future__ import annotations

from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from sandbox.integrations.fakes import recorded_sends
from sandbox.integrations.fakes import reset_fakes
from sandbox.users.tests.factories import UserFactory
from sandbox.users.tests.factories import VerifiedUserFactory

pytestmark = pytest.mark.django_db

VERIFY_URL = "/users/verify-contacts/"


@pytest.fixture(autouse=True)
def _clean_state():
    cache.clear()
    reset_fakes()
    yield
    cache.clear()
    reset_fakes()


def _verified_user(**kwargs):
    now = timezone.now()
    return UserFactory.create(
        email_verified_at=now,
        phone="+919876543210",
        phone_verified_at=now,
        **kwargs,
    )


def test_an_unverified_user_is_sent_to_the_gate(client):
    user = UserFactory.create(phone="+919876543210")
    client.force_login(user)

    response = client.get(reverse("users:redirect"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == VERIFY_URL


def test_a_half_verified_user_is_still_blocked(client):
    user = UserFactory.create(phone="+919876543210", email_verified_at=timezone.now())
    client.force_login(user)

    response = client.get(reverse("users:redirect"))

    assert response.url == VERIFY_URL


def test_a_fully_verified_user_passes_through(client):
    client.force_login(_verified_user())

    response = client.get(reverse("users:redirect"))

    assert response.url != VERIFY_URL


def test_the_gate_page_itself_is_reachable_while_unverified(client):
    client.force_login(UserFactory.create(phone="+919876543210"))

    assert client.get(VERIFY_URL).status_code == HTTPStatus.OK


def test_account_pages_stay_reachable_so_a_user_can_log_out(client):
    client.force_login(UserFactory.create(phone="+919876543210"))

    assert client.get("/accounts/logout/").status_code == HTTPStatus.OK


def test_staff_are_exempt(client):
    user = UserFactory.create(phone="+919876543210", is_staff=True)
    client.force_login(user)

    response = client.get(reverse("users:redirect"))

    assert response.url != VERIFY_URL


def test_anonymous_users_are_untouched(client):
    response = client.get("/")

    assert response.status_code == HTTPStatus.OK


def test_sending_a_code_from_the_gate(client):
    user = UserFactory.create(phone="+919876543210")
    client.force_login(user)

    client.post(VERIFY_URL, {"channel": "EMAIL", "send": ""})

    assert recorded_sends()[-1]["channel"] == "EMAIL"
    assert recorded_sends()[-1]["to"] == user.email


def test_verifying_both_contacts_opens_the_portal(client):
    user = UserFactory.create(phone="+919876543210")
    client.force_login(user)

    for channel, _identity in (("EMAIL", user.email), ("SMS", user.phone)):
        client.post(VERIFY_URL, {"channel": channel, "send": ""})
        code = recorded_sends()[-1]["context"]["code"]
        client.post(VERIFY_URL, {"channel": channel, "code": code, "verify": ""})

    user.refresh_from_db()
    assert user.email_verified_at is not None
    assert user.phone_verified_at is not None
    assert client.get(reverse("users:redirect")).url != VERIFY_URL


def test_a_wrong_code_leaves_the_user_blocked(client):
    user = UserFactory.create(phone="+919876543210")
    client.force_login(user)
    client.post(VERIFY_URL, {"channel": "EMAIL", "send": ""})

    client.post(VERIFY_URL, {"channel": "EMAIL", "code": "000000", "verify": ""})

    user.refresh_from_db()
    assert user.email_verified_at is None
    assert client.get(reverse("users:redirect")).url == VERIFY_URL


# --- the staff branch: TOTP instead of contact OTP ---


def test_staff_without_mfa_is_redirected_to_setup(client):
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("home"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("mfa_activate_totp")


def test_mfa_setup_flow_is_not_blocked_by_the_guard(client):
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("mfa_activate_totp"))

    # allauth asks for reauthentication first; the guard must not loop on it.
    assert response.url.startswith("/accounts/reauthenticate/")


def test_staff_with_mfa_passes_through(client, enable_mfa):
    client.force_login(enable_mfa(UserFactory(is_staff=True)))

    assert client.get(reverse("home")).status_code == HTTPStatus.OK


def test_non_staff_users_are_not_forced_into_mfa(client):
    client.force_login(VerifiedUserFactory())

    assert client.get(reverse("home")).status_code == HTTPStatus.OK


def test_staff_are_never_sent_to_the_contact_gate(client, enable_mfa):
    client.force_login(enable_mfa(UserFactory(is_staff=True)))

    assert client.get(reverse("home")).status_code == HTTPStatus.OK
