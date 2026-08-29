from __future__ import annotations

from http import HTTPStatus

from django.urls import reverse

from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory


def test_organisation_changelist(admin_client, db):
    OrganisationFactory.create()
    response = admin_client.get(reverse("admin:organisations_organisation_changelist"))
    assert response.status_code == HTTPStatus.OK


def test_organisation_change_view(admin_client, db):
    organisation = OrganisationFactory.create()
    url = reverse(
        "admin:organisations_organisation_change",
        kwargs={"object_id": organisation.pk},
    )
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK


def test_product_changelist(admin_client, db):
    ProductFactory.create()
    response = admin_client.get(reverse("admin:organisations_product_changelist"))
    assert response.status_code == HTTPStatus.OK


def test_membership_changelist(admin_client, db):
    MembershipFactory.create()
    response = admin_client.get(reverse("admin:organisations_membership_changelist"))
    assert response.status_code == HTTPStatus.OK
