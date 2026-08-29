from __future__ import annotations

import pytest

from sandbox.organisations.models import Product
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


def test_for_organisation_returns_only_that_organisations_rows():
    org_a = OrganisationFactory.create()
    org_b = OrganisationFactory.create()
    product_a = ProductFactory.create(organisation=org_a)
    ProductFactory.create(organisation=org_b)

    results = Product.objects.for_organisation(org_a)

    assert list(results) == [product_a]


def test_for_organisation_excludes_soft_deleted_rows():
    org = OrganisationFactory.create()
    product = ProductFactory.create(organisation=org)
    product.delete()

    assert not Product.objects.for_organisation(org).exists()
    assert Product.all_objects.filter(organisation=org).exists()
