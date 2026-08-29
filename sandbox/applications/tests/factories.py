from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas.sandbox import IntegrationIntent
from sandbox.applications.schemas.sandbox import PayerCategory
from sandbox.applications.schemas.sandbox import SolutionType
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory

VALID_SANDBOX_DATA = {
    "solution_types": [SolutionType.HMIS.value],
    "integration_intents": [
        IntegrationIntent.ABHA_M1.value,
        IntegrationIntent.HIP_M2.value,
    ],
    "payer_categories": [PayerCategory.TPA.value],
    "use_case_narrative": "Verifying ABHA before dispensing OPD records.",
}


class ApplicationFactory(DjangoModelFactory[Application]):
    reference = factory.Sequence(lambda n: f"SBX-2026-{n:05d}")
    kind = ApplicationKind.SANDBOX
    product = factory.SubFactory(ProductFactory)
    applicant = factory.SubFactory(UserFactory)
    state = ApplicationState.DRAFT
    payload = factory.LazyFunction(
        lambda: {"schema_version": 1, "data": dict(VALID_SANDBOX_DATA)},
    )

    class Meta:
        model = Application
