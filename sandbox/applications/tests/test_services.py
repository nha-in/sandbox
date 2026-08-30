from __future__ import annotations

import re

import pytest

from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationState
from sandbox.applications.services import create_draft
from sandbox.applications.services import create_draft_with_new_product
from sandbox.applications.services import update_draft
from sandbox.applications.tests.factories import VALID_SANDBOX_DATA
from sandbox.applications.tests.factories import ApplicationFactory
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
        "kind": ApplicationKind.SANDBOX,
        "data": dict(VALID_SANDBOX_DATA),
    }
    return create_draft(**{**kwargs, **overrides})


def test_create_draft_generates_a_valid_reference_and_stores_payload():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    application = _create_sandbox_draft(product, applicant)

    assert REFERENCE_PATTERN.match(application.reference)
    assert application.state == ApplicationState.DRAFT
    assert application.product == product
    assert application.payload == {"schema_version": 1, "data": VALID_SANDBOX_DATA}


def test_create_draft_rejects_non_sandbox_kind():
    product = ProductFactory.create()
    applicant = UserFactory.create()

    with pytest.raises(DomainError):
        _create_sandbox_draft(product, applicant, kind=ApplicationKind.HCX)


def test_create_draft_accepts_incomplete_answers():
    """A draft holds work in progress; completeness is SUBMIT's problem."""
    product = ProductFactory.create()
    applicant = UserFactory.create()

    application = _create_sandbox_draft(product, applicant, data={})

    assert application.state == ApplicationState.DRAFT
    assert application.payload == {"schema_version": 1, "data": {}}


def test_create_draft_rejects_an_unrenderable_schema_version():
    """The answers may be missing; the envelope around them may not be broken."""
    product = ProductFactory.create()
    applicant = UserFactory.create()

    with pytest.raises(DomainError):
        create_draft(
            organisation=product.organisation,
            product=product,
            applicant=applicant,
            kind="NOT_A_KIND",
            data={},
        )


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
        kind=ApplicationKind.SANDBOX,
        data=dict(VALID_SANDBOX_DATA),
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
            kind=ApplicationKind.HCX,
            data=dict(VALID_SANDBOX_DATA),
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


def test_update_draft_allowed_in_draft_state():
    application = ApplicationFactory.create(state=ApplicationState.DRAFT)
    new_data = dict(VALID_SANDBOX_DATA, use_case_narrative="Updated narrative.")

    updated = update_draft(application=application, data=new_data)

    assert updated.payload["data"]["use_case_narrative"] == "Updated narrative."


def test_update_draft_allowed_in_sent_back_state():
    application = ApplicationFactory.create(state=ApplicationState.SENT_BACK)
    new_data = dict(VALID_SANDBOX_DATA, use_case_narrative="Revised after send-back.")

    updated = update_draft(application=application, data=new_data)

    assert updated.payload["data"]["use_case_narrative"] == "Revised after send-back."


def test_update_draft_rejected_once_submitted():
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)

    with pytest.raises(DomainError):
        update_draft(application=application, data=dict(VALID_SANDBOX_DATA))


def test_update_draft_accepts_incomplete_answers():
    application = ApplicationFactory.create(state=ApplicationState.DRAFT)

    updated = update_draft(application=application, data={})

    assert updated.payload["data"] == {}
