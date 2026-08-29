from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse

from sandbox.organisations.mixins import ACTIVE_ORGANISATION_SESSION_KEY
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import VerifiedUserFactory

pytestmark = pytest.mark.django_db


def test_get_lists_the_users_organisations(client):
    user = VerifiedUserFactory.create()
    membership = MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.get(reverse("organisations:switch"))

    assert response.status_code == HTTPStatus.OK
    assert membership.organisation.name in response.content.decode()


def test_post_sets_active_organisation_and_redirects(client):
    user = VerifiedUserFactory.create()
    membership = MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("organisations:switch"),
        data={"organisation": str(membership.organisation.external_id)},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert client.session[ACTIVE_ORGANISATION_SESSION_KEY] == membership.organisation_id


def test_post_redirects_to_next_when_safe(client):
    user = VerifiedUserFactory.create()
    membership = MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("organisations:switch"),
        data={
            "organisation": str(membership.organisation.external_id),
            "next": "/about/",
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == "/about/"


def test_post_ignores_unsafe_next_and_falls_back_home(client):
    user = VerifiedUserFactory.create()
    membership = MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("organisations:switch"),
        data={
            "organisation": str(membership.organisation.external_id),
            "next": "https://evil.example/",
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("home")


def test_post_rejects_organisation_the_user_is_not_a_member_of(client):
    user = VerifiedUserFactory.create()
    foreign_org = OrganisationFactory.create()
    client.force_login(user)

    response = client.post(
        reverse("organisations:switch"),
        data={"organisation": str(foreign_org.external_id)},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_anonymous_user_redirected_to_login(client):
    response = client.get(reverse("organisations:switch"))
    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("account_login"))
