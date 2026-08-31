from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db import transaction

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationReferenceCounter
from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_reference_unique_only_among_non_deleted():
    original = ApplicationFactory.create(reference="SBX-2026-00001")
    original.delete()

    recreated = ApplicationFactory.create(reference="SBX-2026-00001")

    assert recreated.pk != original.pk
    assert Application.objects.filter(reference="SBX-2026-00001").count() == 1


@pytest.mark.parametrize("field", ["state", "workflow_key"])
def test_the_database_no_longer_polices_the_enums(field):
    # Deliberate: states and kinds are defined by the workflow in code, so a
    # CHECK constraint here would mean a migration for every new state. The
    # column is a plain char field; the engine is what refuses a bad value.
    application = ApplicationFactory.build(
        **{field: "NOT_A_REAL_VALUE"},
        product=ProductFactory.create(),
        applicant=UserFactory.create(),
    )

    application.save()

    application.refresh_from_db()
    assert getattr(application, field) == "NOT_A_REAL_VALUE"


def test_duplicate_in_flight_application_for_same_product_and_workflow_rejected():
    product = ProductFactory.create()
    ApplicationFactory.create(product=product, state=ApplicationState.DRAFT)
    duplicate = ApplicationFactory.build(
        product=product,
        applicant=UserFactory.create(),
        state=ApplicationState.SUBMITTED,
    )

    with transaction.atomic(), pytest.raises(IntegrityError):
        duplicate.save()


def test_an_exit_may_run_alongside_the_application_it_exits():
    # Same product, different workflow: the slot is per (product, workflow_key),
    # which is what lets an exit be in review while the ABDM app stays live.
    product = ProductFactory.create()
    ApplicationFactory.create(product=product, state=ApplicationState.DRAFT)

    exit_application = ApplicationFactory.create(
        product=product,
        workflow_key="ABDM_EXIT",
        state=ApplicationState.DRAFT,
    )

    assert exit_application.pk is not None


@pytest.mark.parametrize(
    "non_blocking_state",
    [ApplicationState.REJECTED, ApplicationState.WITHDRAWN],
)
def test_reapplying_allowed_after_rejected_or_withdrawn(non_blocking_state):
    product = ProductFactory.create()
    ApplicationFactory.create(product=product, state=non_blocking_state)

    second = ApplicationFactory.create(product=product, state=ApplicationState.DRAFT)

    assert second.pk is not None


def test_second_product_gets_its_own_application():
    first_product = ProductFactory.create()
    second_product = ProductFactory.create()
    ApplicationFactory.create(product=first_product)

    second = ApplicationFactory.create(product=second_product)

    assert second.pk is not None


def test_reference_counter_str():
    counter = ApplicationReferenceCounter.objects.create(year=2026, last_value=3)
    assert str(counter) == "2026: 3"
