"""Isolated from test_services.py: needs `transaction=True` to run threads
against real, separately-committed connections — proves `_next_reference`'s
race-safety claim rather than asserting it by code inspection alone.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection

from sandbox.applications.services import create_draft
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory


@pytest.mark.django_db(transaction=True)
def test_reference_generation_is_race_safe_across_concurrent_transactions():
    applicant = UserFactory.create()

    references: list[str] = []
    errors: list[Exception] = []

    def _create():
        try:
            product = ProductFactory.create()
            application = create_draft(
                organisation=product.organisation,
                product=product,
                applicant=applicant,
                workflow_key="ABDM",
            )
            references.append(application.reference)
        except Exception as exc:  # noqa: BLE001 - surfaced via `errors` below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=_create) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(references) == len(set(references)) == 5  # noqa: PLR2004
