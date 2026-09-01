from __future__ import annotations

import re

import pytest

from sandbox.applications.models import ApplicationState
from sandbox.applications.services import create_draft
from sandbox.applications.services import create_draft_with_new_product
from sandbox.organisations.models import Product
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError

pytestmark = pytest.mark.django_db

REFERENCE_PATTERN = re.compile(r"^SBX-\d{4}-\d{5}$")


def _create_sandbox_draft(product, applicant, **overrides):
    kwargs = {
        "organisation": product.organisation,
        "product": product,
        "applicant": applicant,
        "workflow_key": "ABDM",
    }
    return create_draft(**{**kwargs, **overrides})


def test_create_draft_opens_an_empty_application_bound_to_its_workflow():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    application = _create_sandbox_draft(product, applicant)

    assert REFERENCE_PATTERN.match(application.reference)
    assert application.state == ApplicationState.DRAFT
    assert application.product == product
    # answers arrive later, one form submission at a time
    assert application.workflow_key == "ABDM"
    assert not application.submissions.exists()


def test_create_draft_rejects_non_sandbox_kind():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    with pytest.raises(DomainError):
        _create_sandbox_draft(product, applicant, workflow_key="HCX")


def test_create_draft_rejects_a_product_from_another_organisation():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    with pytest.raises(DomainError):
        _create_sandbox_draft(
            product,
            applicant,
            organisation=OrganisationFactory.create(),
        )


def test_create_draft_accepts_a_product_created_in_the_same_submit():
    organisation = OrganisationFactory.create()
    applicant = UserFactory.create()
    product = ProductFactory.create(organisation=organisation)

    application = _create_sandbox_draft(product, applicant)

    assert application.product == product


def test_create_draft_creates_the_product_when_given_a_name():
    organisation = OrganisationFactory.create()
    applicant = UserFactory.create()

    application = create_draft_with_new_product(
        organisation=organisation,
        product_name="Brand New HMIS",
        applicant=applicant,
        workflow_key="ABDM",
    )

    assert application.product.name == "Brand New HMIS"
    assert application.product.slug == "brand-new-hmis"
    assert application.product.organisation == organisation


def test_create_draft_does_not_leave_an_orphan_product_when_the_kind_is_invalid():
    organisation = OrganisationFactory.create()
    applicant = UserFactory.create()

    with pytest.raises(DomainError):
        create_draft_with_new_product(
            organisation=organisation,
            product_name="Never Persisted",
            applicant=applicant,
            workflow_key="HCX",
        )

    assert not Product.objects.filter(name="Never Persisted").exists()


def test_create_draft_references_are_sequential_within_a_year():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    first = _create_sandbox_draft(product, applicant)
    second = _create_sandbox_draft(ProductFactory.create(), applicant)

    first_seq = int(first.reference.rsplit("-", 1)[1])
    second_seq = int(second.reference.rsplit("-", 1)[1])
    assert second_seq == first_seq + 1
