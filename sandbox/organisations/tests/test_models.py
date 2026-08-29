from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.models import NatureOfEntity
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import OrganisationCategory
from sandbox.organisations.models import OrganisationKind
from sandbox.organisations.models import OrganisationOwnership
from sandbox.organisations.models import Product
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_organisation_slug_unique_only_among_non_deleted():
    original = OrganisationFactory.create(slug="dupe-slug")
    original.delete()

    recreated = OrganisationFactory.create(slug="dupe-slug")

    assert recreated.pk != original.pk
    assert Organisation.objects.filter(slug="dupe-slug").count() == 1


def test_organisation_kind_check_constraint_rejects_invalid_value():
    organisation = OrganisationFactory.build(kind="NOT_A_REAL_KIND")
    with transaction.atomic(), pytest.raises(IntegrityError):
        organisation.save()


def test_organisation_verification_state_check_constraint_rejects_invalid_value():
    organisation = OrganisationFactory.build(verification_state="NOT_A_REAL_STATE")
    with transaction.atomic(), pytest.raises(IntegrityError):
        organisation.save()


def test_organisation_kind_choices_are_valid():
    organisation = OrganisationFactory.create(kind=OrganisationKind.INDIVIDUAL)
    assert organisation.kind == OrganisationKind.INDIVIDUAL


@pytest.mark.parametrize(
    "field",
    ["nature_of_entity", "ownership", "category"],
)
def test_organisation_optional_enum_rejects_invalid_value(field):
    organisation = OrganisationFactory.build(**{field: "NOT_A_REAL_VALUE"})
    with transaction.atomic(), pytest.raises(IntegrityError):
        organisation.save()


@pytest.mark.parametrize(
    "field",
    ["nature_of_entity", "ownership", "category"],
)
def test_organisation_optional_enum_allows_blank(field):
    organisation = OrganisationFactory.create(**{field: ""})
    assert getattr(organisation, field) == ""


def test_organisation_legacy_enum_values_are_accepted():
    organisation = OrganisationFactory.create(
        nature_of_entity=NatureOfEntity.LLP,
        ownership=OrganisationOwnership.PRIVATE,
        category=OrganisationCategory.DIAGNOSTIC_LABS,
    )
    assert organisation.nature_of_entity == NatureOfEntity.LLP
    assert organisation.ownership == OrganisationOwnership.PRIVATE
    assert organisation.category == OrganisationCategory.DIAGNOSTIC_LABS


def test_organisation_gst_number_validator_rejects_malformed_gstin():
    organisation = OrganisationFactory.build(gst_number="NOT-A-GSTIN")
    with pytest.raises(ValidationError):
        organisation.full_clean()


def test_organisation_gst_number_validator_accepts_a_well_formed_gstin():
    organisation = OrganisationFactory.build(gst_number="27AAPFU0939F1ZV")
    organisation.full_clean()


def test_organisation_gst_number_may_be_blank():
    organisation = OrganisationFactory.build(gst_number="")
    organisation.full_clean()


def test_organisation_registered_in_india_defaults_to_unknown():
    assert OrganisationFactory.create().registered_in_india is None


def test_product_unique_organisation_slug_only_among_non_deleted():
    organisation = OrganisationFactory.create()
    original = ProductFactory.create(organisation=organisation, slug="dupe-slug")
    original.delete()

    recreated = ProductFactory.create(organisation=organisation, slug="dupe-slug")

    assert recreated.pk != original.pk
    assert (
        Product.objects.filter(organisation=organisation, slug="dupe-slug").count() == 1
    )


def test_product_same_slug_allowed_across_different_organisations():
    ProductFactory.create(slug="shared-slug")
    ProductFactory.create(slug="shared-slug")

    assert Product.objects.filter(slug="shared-slug").count() == 2  # noqa: PLR2004


def test_membership_unique_organisation_user_only_among_non_deleted():
    organisation = OrganisationFactory.create()
    user = UserFactory.create()
    original = MembershipFactory.create(organisation=organisation, user=user)
    original.delete()

    recreated = MembershipFactory.create(organisation=organisation, user=user)

    assert recreated.pk != original.pk
    assert Membership.objects.filter(organisation=organisation, user=user).count() == 1


def test_membership_role_check_constraint_rejects_invalid_value():
    organisation = OrganisationFactory.create()
    user = UserFactory.create()
    membership = MembershipFactory.build(
        organisation=organisation,
        user=user,
        role="NOT_A_REAL_ROLE",
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        membership.save()


def test_membership_role_choices_are_valid():
    membership = MembershipFactory.create(role=MembershipRole.DEVELOPER)
    assert membership.role == MembershipRole.DEVELOPER
