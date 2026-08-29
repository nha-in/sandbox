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


def test_kind_check_constraint_rejects_invalid_value():
    # build() with an unsaved related FK raises ValueError before ever
    # reaching the DB, so product/applicant are pre-created here (A2 gotcha).
    application = ApplicationFactory.build(
        kind="NOT_A_REAL_KIND",
        product=ProductFactory.create(),
        applicant=UserFactory.create(),
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        application.save()


def test_state_check_constraint_rejects_invalid_value():
    application = ApplicationFactory.build(
        state="NOT_A_REAL_STATE",
        product=ProductFactory.create(),
        applicant=UserFactory.create(),
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        application.save()


def test_duplicate_live_application_for_same_product_and_kind_rejected():
    product = ProductFactory.create()
    ApplicationFactory.create(product=product, state=ApplicationState.DRAFT)
    duplicate = ApplicationFactory.build(
        product=product,
        applicant=UserFactory.create(),
        state=ApplicationState.SUBMITTED,
    )

    with transaction.atomic(), pytest.raises(IntegrityError):
        duplicate.save()


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
