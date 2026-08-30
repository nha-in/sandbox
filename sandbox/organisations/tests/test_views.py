from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse

from sandbox.catalog.selectors import districts_for_state
from sandbox.catalog.selectors import state_choices
from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.models import NatureOfEntity
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import OrganisationCategory
from sandbox.organisations.models import OrganisationKind
from sandbox.organisations.models import OrganisationOwnership
from sandbox.organisations.models import OrganisationVerificationState
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import VerifiedUserFactory

pytestmark = pytest.mark.django_db

EXPECTED_COLLIDING_ORGS = 2


def _profile_post(**overrides) -> dict[str, str]:
    state_code = state_choices()[0][0]
    return {
        "nature_of_entity": NatureOfEntity.values[0],
        "ownership": OrganisationOwnership.values[0],
        "category": OrganisationCategory.values[0],
        "gst_number": "",
        "registered_in_india": "true",
        "website": "https://example.test",
        "address_line1": "1 Test Road",
        "address_line2": "",
        "address_city": "Kochi",
        "address_pincode": "682001",
        "lgd_state_code": state_code,
        "lgd_district_code": districts_for_state(state_code)[0][0],
        **overrides,
    }


def _create_post(**overrides) -> dict[str, str]:
    return _profile_post(
        **{
            "name": "Ohc Network",
            "kind": OrganisationKind.ORGANIZATION,
            **overrides,
        },
    )


# --- creation ---------------------------------------------------------------


def test_a_user_with_no_organisation_is_offered_one(client):
    """Sign-up creates a user with no tenant. Without this the account is a dead
    end: no membership means no wizard, and nothing else creates an organisation."""
    user = VerifiedUserFactory.create()
    client.force_login(user)

    response = client.get(
        reverse("users:detail", kwargs={"external_id": user.external_id}),
    )
    assert reverse("organisations:create") in response.content.decode()

    response = client.post(reverse("organisations:create"), data=_create_post())

    assert response.status_code == HTTPStatus.FOUND
    membership = Membership.objects.get(user=user)
    assert membership.role == MembershipRole.OWNER
    assert membership.organisation.name == "Ohc Network"
    # the wizard is entered inside the tenant just created
    assert response["Location"] == (
        f"{reverse('applications:step_product')}?org={membership.organisation.external_id}"
    )
    # creating one grants no standing — staff still have to verify it
    assert (
        membership.organisation.verification_state
        == OrganisationVerificationState.PENDING
    )


def test_an_organisation_cannot_be_created_without_a_profile(client):
    """Completeness is enforced at creation, so nothing downstream has to guard
    against a half-filled organisation."""
    user = VerifiedUserFactory.create()
    client.force_login(user)

    response = client.post(
        reverse("organisations:create"),
        data={"name": "Ohc Network", "kind": OrganisationKind.ORGANIZATION},
    )

    assert response.status_code == HTTPStatus.OK
    assert not Organisation.objects.filter(name="Ohc Network").exists()
    assert set(response.context["form"].errors) >= {
        "nature_of_entity",
        "ownership",
        "category",
        "address_line1",
        "address_city",
        "address_pincode",
        "lgd_state_code",
        "lgd_district_code",
    }


def test_organisation_slugs_do_not_collide(client):
    first = VerifiedUserFactory.create()
    second = VerifiedUserFactory.create()
    for user in (first, second):
        client.force_login(user)
        client.post(
            reverse("organisations:create"),
            data=_create_post(name="Same Name Ltd"),
        )

    slugs = list(
        Organisation.objects.filter(name="Same Name Ltd").values_list(
            "slug",
            flat=True,
        ),
    )
    assert len(slugs) == len(set(slugs)) == EXPECTED_COLLIDING_ORGS


# --- profile ----------------------------------------------------------------


def test_profile_is_editable_by_any_member(client):
    membership = MembershipFactory.create(
        user=VerifiedUserFactory.create(),
        role=MembershipRole.DEVELOPER,
    )
    client.force_login(membership.user)

    response = client.post(
        reverse("organisations:profile"),
        data=_profile_post(address_city="Thrissur"),
    )

    assert response.status_code == HTTPStatus.FOUND
    membership.organisation.refresh_from_db()
    assert membership.organisation.address_city == "Thrissur"


def test_profile_reopens_with_the_saved_answers(client):
    """`registered_in_india` is the trap: the model hands the form a Python bool,
    which matches neither string choice, so a saved Yes rendered blank."""
    membership = MembershipFactory.create(user=VerifiedUserFactory.create())
    client.force_login(membership.user)
    client.post(reverse("organisations:profile"), data=_profile_post())

    response = client.get(reverse("organisations:profile"))

    form = response.context["form"]
    assert form["registered_in_india"].value() == "true"
    assert form["address_city"].value() == "Kochi"


# --- choosing ---------------------------------------------------------------


def test_choose_lists_the_users_organisations_as_links(client):
    user = VerifiedUserFactory.create()
    first = MembershipFactory.create(user=user)
    second = MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.get(reverse("organisations:choose"))

    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    for membership in (first, second):
        assert f"org={membership.organisation.external_id}" in body


def test_choose_ignores_an_unsafe_next(client):
    membership = MembershipFactory.create(user=VerifiedUserFactory.create())
    client.force_login(membership.user)

    response = client.get(
        reverse("organisations:choose"),
        {"next": "https://evil.test/steal"},
    )

    assert "evil.test" not in response.content.decode()


# --- shell ------------------------------------------------------------------


def test_shell_offers_a_way_back_to_the_picker(client):
    """The picker used to be reachable only by the automatic redirect, so after
    choosing once a multi-org user was stuck."""
    user = VerifiedUserFactory.create()
    first = MembershipFactory.create(user=user)
    MembershipFactory.create(user=user, organisation=OrganisationFactory.create())
    client.force_login(user)

    response = client.get(
        reverse("organisations:profile"),
        {"org": str(first.organisation.external_id)},
    )

    assert response.context["active_organisation"] == first.organisation
    assert response.context["has_multiple_organisations"] is True
    assert reverse("organisations:choose") in response.content.decode()


def test_shell_links_a_member_to_their_dashboard(client):
    """The application flow had no inbound link at all — reachable only by typing
    the URL. The dashboard is the entry point; the wizard hangs off its CTA."""
    user = VerifiedUserFactory.create()
    MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.get(
        reverse("users:detail", kwargs={"external_id": user.external_id}),
    )

    assert reverse("applications:index") in response.content.decode()


def test_shell_shows_no_wizard_link_to_a_non_member(client):
    user = VerifiedUserFactory.create()
    client.force_login(user)

    response = client.get(
        reverse("users:detail", kwargs={"external_id": user.external_id}),
    )

    assert "is_organisation_member" not in response.context
    assert reverse("applications:index") not in response.content.decode()


def test_choose_offers_creating_another_organisation(client):
    """Self-service creation, limits deferred (open question 6). Without a link
    here a one-org user could not reach the create screen at all."""
    membership = MembershipFactory.create(user=VerifiedUserFactory.create())
    client.force_login(membership.user)

    response = client.get(reverse("organisations:choose"))

    assert reverse("organisations:create") in response.content.decode()


def test_a_single_org_member_can_reach_the_organisation_list(client):
    """Gating the list on >1 membership was a chicken-and-egg: you needed two
    organisations to reach the only screen that lets you make a second."""
    membership = MembershipFactory.create(user=VerifiedUserFactory.create())
    client.force_login(membership.user)

    response = client.get(
        reverse("users:detail", kwargs={"external_id": membership.user.external_id}),
    )

    assert reverse("organisations:choose") in response.content.decode()
