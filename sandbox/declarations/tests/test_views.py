"""Download authorization. The bucket is private, so this view is the only door."""

from __future__ import annotations

import pytest
from allauth.mfa.totp.internal import auth as totp_auth
from django.test import Client
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.catalog.tests.factories import MilestoneFactory
from sandbox.declarations import services
from sandbox.declarations.tests.conftest import upload
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import VerifiedUserFactory

pytestmark = pytest.mark.django_db

HTTP_FOUND = 302
HTTP_NOT_FOUND = 404


@pytest.fixture
def document(mock_s3, application, milestone, member):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload()],
        actor=member,
    )
    return declaration.documents.get()


def _url(document):
    return reverse(
        "declarations:document_download",
        kwargs={"external_id": document.external_id},
    )


def _client(user=None):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def test_an_org_member_is_redirected_to_a_presigned_url(document, member):
    response = _client(member).get(_url(document))

    assert response.status_code == HTTP_FOUND
    location = response.headers["Location"]
    assert document.storage_key in location
    assert "X-Amz-Signature=" in location


def test_the_redirect_never_points_at_our_own_domain(document, member):
    """A public URL would defeat the private bucket; it must go to storage."""
    location = _client(member).get(_url(document)).headers["Location"]
    assert location.startswith("https://")
    assert "testserver" not in location


def test_a_member_of_another_organisation_gets_404(document, db):
    """404, not 403 — a 403 would confirm the document exists."""
    stranger = VerifiedUserFactory.create()
    MembershipFactory.create(organisation=OrganisationFactory.create(), user=stranger)

    response = _client(stranger).get(_url(document))
    assert response.status_code == HTTP_NOT_FOUND


def test_staff_without_a_membership_get_404(document, db):
    """Console access is a separate surface; C5 brings its own view."""
    staff = VerifiedUserFactory.create(is_staff=True, is_superuser=True)
    # TOTP, or the verification gate answers before the view does
    totp_auth.TOTP.activate(staff, totp_auth.generate_totp_secret())

    response = _client(staff).get(_url(document))
    assert response.status_code == HTTP_NOT_FOUND


def test_an_anonymous_visitor_is_sent_to_login(document):
    response = _client().get(_url(document))

    assert response.status_code == HTTP_FOUND
    assert reverse("account_login") in response.headers["Location"]


def test_a_document_in_a_second_product_of_the_same_org_is_reachable(
    mock_s3,
    organisation,
    member,
):
    """Scoping is by organisation, not by application."""
    other = ApplicationFactory.create(
        product=ProductFactory.create(organisation=organisation),
        applicant=member,
        state=ApplicationState.PROVISIONED,
    )

    declaration = services.submit_milestone_declaration(
        application=other,
        milestone=MilestoneFactory.create(),
        files=[upload()],
        actor=member,
    )

    response = _client(member).get(_url(declaration.documents.get()))
    assert response.status_code == HTTP_FOUND


def test_an_unknown_id_gets_404(member, db):
    url = reverse(
        "declarations:document_download",
        kwargs={"external_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert _client(member).get(url).status_code == HTTP_NOT_FOUND


def test_a_soft_deleted_document_is_gone(document, member):
    document.delete()
    assert _client(member).get(_url(document)).status_code == HTTP_NOT_FOUND
