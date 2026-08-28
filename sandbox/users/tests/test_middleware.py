import pytest
from django.urls import reverse

from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_staff_without_mfa_is_redirected_to_setup(client):
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("home"))

    assert response.status_code == 302
    assert response.url == reverse("mfa_activate_totp")


def test_mfa_setup_flow_is_not_blocked_by_the_guard(client):
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("mfa_activate_totp"))

    # allauth asks for reauthentication first; the guard must not loop on it.
    assert response.url.startswith("/accounts/reauthenticate/")


def test_staff_with_mfa_passes_through(client, enable_mfa):
    client.force_login(enable_mfa(UserFactory(is_staff=True)))

    assert client.get(reverse("home")).status_code == 200


def test_non_staff_users_are_not_forced_into_mfa(client):
    client.force_login(UserFactory())

    assert client.get(reverse("home")).status_code == 200
