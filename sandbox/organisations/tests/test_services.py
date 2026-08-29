from __future__ import annotations

import pytest

from sandbox.organisations.services import create_product
from sandbox.organisations.tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db


def test_create_product_derives_the_slug_from_the_name():
    product = create_product(
        organisation=OrganisationFactory.create(),
        name="My HMIS Platform",
    )
    assert product.slug == "my-hmis-platform"


def test_duplicate_names_in_one_organisation_get_distinct_slugs():
    organisation = OrganisationFactory.create()

    first = create_product(organisation=organisation, name="My HMIS")
    second = create_product(organisation=organisation, name="My HMIS")
    third = create_product(organisation=organisation, name="My HMIS")

    assert [first.slug, second.slug, third.slug] == [
        "my-hmis",
        "my-hmis-2",
        "my-hmis-3",
    ]


def test_the_same_name_in_another_organisation_keeps_the_plain_slug():
    create_product(organisation=OrganisationFactory.create(), name="My HMIS")

    other = create_product(organisation=OrganisationFactory.create(), name="My HMIS")

    assert other.slug == "my-hmis"


def test_a_soft_deleted_product_frees_its_slug():
    organisation = OrganisationFactory.create()
    create_product(organisation=organisation, name="My HMIS").delete()

    recreated = create_product(organisation=organisation, name="My HMIS")

    assert recreated.slug == "my-hmis"


def test_a_name_with_no_slug_characters_falls_back():
    product = create_product(
        organisation=OrganisationFactory.create(),
        name="!!!",
    )
    assert product.slug == "product"
