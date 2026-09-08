"""Every status renders a page, for the applicant and for the review team.

Carried over from the pre-port `tests/test_dashboard.py`, whose load-bearing
test was this one: a detail page that falls through to a blank card on one
status is the kind of bug nobody notices until an integrator is sitting on it.
The rest of that module tested a screen the engine replaced, and went with it.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import Client
from django.urls import reverse

from sandbox.experiences.registry import registry
from sandbox.experiences.services import create_application
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"
STATUSES = [status.key for status in registry.get(APPLICATION_TYPE).statuses]


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@vendor.in")


@pytest.fixture
def application(owner):
    organisation = OrganisationFactory(onboarded=True)
    Membership.objects.create(
        organisation=organisation,
        user=owner,
        role=Role.OWNER,
    )
    return create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )


def _at(application, status):
    application.status = status
    application.save(update_fields=["status", "updated_at"])
    return application


@pytest.mark.parametrize("status", STATUSES)
def test_the_applicant_detail_page_renders_on_every_status(owner, application, status):
    client = Client()
    client.force_login(owner)

    response = client.get(
        reverse(
            "experiences:detail",
            kwargs={"reference": _at(application, status).reference},
        ),
    )

    assert response.status_code == HTTPStatus.OK
    definition = response.context["status_definition"]
    assert definition is not None, f"{status} has no status definition"
    assert str(definition.label) in response.content.decode()


@pytest.mark.parametrize("status", STATUSES)
def test_the_console_detail_page_renders_on_every_status(
    application,
    enable_mfa,
    status,
):
    reviewer = review_role_holder()
    reviewer.is_staff = True
    reviewer.save(update_fields=["is_staff"])
    # Making an account staff subjects it to StaffMfaRequiredMiddleware.
    enable_mfa(reviewer)
    client = Client()
    client.force_login(reviewer)

    response = client.get(
        reverse(
            "staff:application-detail",
            kwargs={"reference": _at(application, status).reference},
        ),
    )

    assert response.status_code == HTTPStatus.OK
    assert str(response.context["status_definition"].label) in response.content.decode()


@pytest.mark.parametrize("status", STATUSES)
def test_the_dashboard_renders_every_status(owner, application, status):
    """The dashboard reuses the list's status badge, so an unmapped status
    would blank the row rather than the page."""
    client = Client()
    client.force_login(owner)

    response = client.get(reverse("dashboard"))

    assert response.status_code == HTTPStatus.OK
    listed = list(response.context["applications"])
    assert listed == [_at(application, status)]
    assert str(listed[0].status_definition.label) in response.content.decode()
