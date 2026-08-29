from __future__ import annotations

import pytest

from sandbox.applications.models import Application
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


def test_for_organisation_returns_only_that_organisations_rows_via_product():
    org_a = OrganisationFactory.create()
    org_b = OrganisationFactory.create()
    application_a = ApplicationFactory.create(
        product=ProductFactory.create(organisation=org_a),
    )
    ApplicationFactory.create(product=ProductFactory.create(organisation=org_b))

    results = Application.objects.for_organisation(org_a)

    assert list(results) == [application_a]


def test_for_organisation_excludes_soft_deleted_rows():
    org = OrganisationFactory.create()
    application = ApplicationFactory.create(
        product=ProductFactory.create(organisation=org),
    )
    application.delete()

    assert not Application.objects.for_organisation(org).exists()
    assert Application.all_objects.filter(product__organisation=org).exists()
