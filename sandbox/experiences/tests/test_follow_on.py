"""Starting an exit from the sandbox access it is about (plan 12 §1.2).

The sandbox access is the container in the *navigation*, not the schema.
Arriving from it is how the applicant says which credentials this exit
concerns, so no form asks them again — and the reference cannot be edited
afterwards, which a form field would have allowed.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse

from sandbox.experiences.models import ApplicationInstance
from sandbox.experiences.selectors import startable_definitions
from sandbox.experiences.services import create_application
from sandbox.experiences.tests.factories import provisioned_sandbox_access
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SANDBOX_ACCESS_TYPE = "abdm_sandbox_access"
MILESTONE_EXIT_TYPE = "abdm_milestone_exit"


@pytest.fixture
def organisation(db):
    return OrganisationFactory(onboarded=True, name="Sunrise Health Systems")


@pytest.fixture
def owner(organisation):
    user = UserFactory(email="owner@vendor.in")
    Membership.objects.create(organisation=organisation, user=user, role=Role.OWNER)
    return user


@pytest.fixture
def sandbox_access(owner, organisation):
    return provisioned_sandbox_access(owner, organisation)


def _url(reference):
    return reverse(
        "experiences:start-follow-on",
        kwargs={"reference": reference, "application_type": MILESTONE_EXIT_TYPE},
    )


class TestStartingFromTheSandboxAccess:
    def test_it_records_the_predecessor_and_carries_the_product(
        self,
        client,
        owner,
        sandbox_access,
    ):
        client.force_login(owner)

        response = client.post(_url(sandbox_access.reference))

        created = ApplicationInstance.objects.get(
            application_type=MILESTONE_EXIT_TYPE,
        )
        assert response.status_code == HTTPStatus.FOUND
        assert created.metadata["predecessor"] == sandbox_access.reference
        assert created.product_id == sandbox_access.product_id

    def test_the_detail_page_offers_it(self, client, owner, sandbox_access):
        client.force_login(owner)

        body = client.get(
            reverse(
                "experiences:detail",
                kwargs={"reference": sandbox_access.reference},
            ),
        ).content.decode()

        assert _url(sandbox_access.reference) in body

    def test_a_sandbox_access_with_no_credentials_offers_nothing(
        self,
        client,
        owner,
        organisation,
    ):
        """An exit is about credentials; there is nothing to file against a
        registration that has none."""
        unprovisioned = create_application(
            application_type=SANDBOX_ACCESS_TYPE,
            organisation=organisation,
            user=owner,
        )
        client.force_login(owner)

        body = client.get(
            reverse(
                "experiences:detail",
                kwargs={"reference": unprovisioned.reference},
            ),
        ).content.decode()
        posted = client.post(_url(unprovisioned.reference))

        assert _url(unprovisioned.reference) not in body
        assert posted.status_code == HTTPStatus.NOT_FOUND

    def test_another_organisations_sandbox_access_is_a_404(
        self,
        client,
        owner,
        organisation,
    ):
        stranger_org = OrganisationFactory(onboarded=True, name="Northwind")
        outsider = UserFactory(email="other@vendor.in")
        Membership.objects.create(
            organisation=stranger_org,
            user=outsider,
            role=Role.OWNER,
        )
        theirs = provisioned_sandbox_access(outsider, stranger_org)
        client.force_login(owner)

        assert client.post(_url(theirs.reference)).status_code == (HTTPStatus.NOT_FOUND)

    def test_the_exit_lists_where_it_came_from(self, client, owner, sandbox_access):
        client.force_login(owner)
        client.post(_url(sandbox_access.reference))
        created = ApplicationInstance.objects.get(
            application_type=MILESTONE_EXIT_TYPE,
        )

        body = client.get(
            reverse("experiences:detail", kwargs={"reference": created.reference}),
        ).content.decode()

        assert sandbox_access.reference in body

    def test_the_sandbox_access_lists_what_was_filed_against_it(
        self,
        client,
        owner,
        sandbox_access,
    ):
        client.force_login(owner)
        client.post(_url(sandbox_access.reference))
        created = ApplicationInstance.objects.get(
            application_type=MILESTONE_EXIT_TYPE,
        )

        body = client.get(
            reverse(
                "experiences:detail",
                kwargs={"reference": sandbox_access.reference},
            ),
        ).content.decode()

        assert created.reference in body


class TestWhatIsOfferedAsAStart:
    def test_the_exit_is_never_a_top_level_start(self, organisation):
        """It used to be: the page opened and the submit 403'd."""
        keys = {d.key for d in startable_definitions(organisation)}

        assert keys == {SANDBOX_ACCESS_TYPE}

    def test_it_stays_that_way_once_credentials_exist(
        self,
        organisation,
        sandbox_access,
    ):
        """`can_start` passing does not make it a *top-level* start — it is
        reachable only from the application it is about."""
        keys = {d.key for d in startable_definitions(organisation)}

        assert MILESTONE_EXIT_TYPE not in keys
