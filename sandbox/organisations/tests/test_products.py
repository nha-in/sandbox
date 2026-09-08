"""`Product` and its matcher (plan 12 §1.2).

The table exists because product identity was living in a form submission's
JSON, with a denormalised copy on `metadata` kept solely so the list could be
filtered. How an application acquires one is `experiences`' business and is
tested there; this is the model and the matching rule.
"""

from __future__ import annotations

import pytest

from sandbox.organisations.models import Product
from sandbox.organisations.services import match_or_create_product
from sandbox.organisations.tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db

TWO_VENDORS = 2


@pytest.fixture
def organisation(db):
    return OrganisationFactory(onboarded=True, name="Sunrise Health Systems")


class TestMatching:
    def test_the_same_product_registered_twice_converges_on_one_row(
        self,
        organisation,
    ):
        """A sixth of legacy organisations registered more than once, most of
        them for the same product."""
        first = match_or_create_product(organisation=organisation, name="Arogya HMIS")
        second = match_or_create_product(organisation=organisation, name="arogya hmis")

        assert first == second
        assert Product.objects.count() == 1

    def test_punctuation_and_spacing_do_not_make_a_second_product(self, organisation):
        match_or_create_product(organisation=organisation, name="Arogya-HMIS")
        match_or_create_product(organisation=organisation, name="  Arogya  HMIS  ")

        assert Product.objects.count() == 1

    def test_two_vendors_may_both_call_a_product_hmis(self, db):
        """Uniqueness is per organisation, not global."""
        one = OrganisationFactory(onboarded=True, name="Sunrise")
        two = OrganisationFactory(onboarded=True, name="Northwind")

        match_or_create_product(organisation=one, name="HMIS")
        match_or_create_product(organisation=two, name="HMIS")

        assert Product.objects.count() == TWO_VENDORS

    def test_a_blank_name_creates_nothing(self, organisation):
        """Most legacy registrations name no product, and a placeholder would be
        indistinguishable from a real one (§1.2)."""
        assert match_or_create_product(organisation=organisation, name="") is None
        assert match_or_create_product(organisation=organisation, name="   ") is None
        assert Product.objects.count() == 0

    def test_a_name_of_only_punctuation_creates_nothing(self, organisation):
        assert match_or_create_product(organisation=organisation, name="---") is None
        assert Product.objects.count() == 0


class TestSlug:
    def test_a_clashing_name_within_one_organisation_gets_a_numbered_slug(
        self,
        organisation,
    ):
        """Only reachable by writing the model directly — the matcher would
        have returned the first — so the fallback is pinned here."""
        first = Product.objects.create(organisation=organisation, name="HMIS")
        second = Product.objects.create(organisation=organisation, name="H.M.I.S.")

        assert first.slug == "hmis"
        assert second.slug == "hmis-2"
