from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.applications.models import ApplicationState
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.programmes.abdm import IntegrationIntent
from sandbox.programmes.abdm import PayerCategory
from sandbox.programmes.abdm import RegistrationSolutionType as SolutionType
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
    workflow_key = "ABDM"
    product = factory.SubFactory(ProductFactory)
    applicant = factory.SubFactory(UserFactory)
    state = ApplicationState.DRAFT

    class Meta:
        model = Application

    @factory.post_generation
    def registered(obj: Application, create, extracted, **kwargs):  # noqa: N805
        """Most tests want an application someone has actually filled in.

        Pass `registered=False` when the test is about one that nobody has yet
        — the engine's own guards are exactly that case.
        """
        if not create or extracted is False:
            return
        ApplicationFormSubmission.objects.create(
            application=obj,
            form_key="REGISTRATION",
            round=obj.round,
            data=dict(VALID_SANDBOX_DATA),
            is_current=True,
            submitted_by=obj.applicant,
        )
